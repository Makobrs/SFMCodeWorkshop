# Generated from SFML.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .SFMLParser import SFMLParser
else:
    from SFMLParser import SFMLParser

# This class defines a complete listener for a parse tree produced by SFMLParser.
class SFMLListener(ParseTreeListener):

    # Enter a parse tree produced by SFMLParser#program.
    def enterProgram(self, ctx:SFMLParser.ProgramContext):
        pass

    # Exit a parse tree produced by SFMLParser#program.
    def exitProgram(self, ctx:SFMLParser.ProgramContext):
        pass


    # Enter a parse tree produced by SFMLParser#name.
    def enterName(self, ctx:SFMLParser.NameContext):
        pass

    # Exit a parse tree produced by SFMLParser#name.
    def exitName(self, ctx:SFMLParser.NameContext):
        pass


    # Enter a parse tree produced by SFMLParser#TimerTrigger.
    def enterTimerTrigger(self, ctx:SFMLParser.TimerTriggerContext):
        pass

    # Exit a parse tree produced by SFMLParser#TimerTrigger.
    def exitTimerTrigger(self, ctx:SFMLParser.TimerTriggerContext):
        pass


    # Enter a parse tree produced by SFMLParser#PulseTrigger.
    def enterPulseTrigger(self, ctx:SFMLParser.PulseTriggerContext):
        pass

    # Exit a parse tree produced by SFMLParser#PulseTrigger.
    def exitPulseTrigger(self, ctx:SFMLParser.PulseTriggerContext):
        pass


    # Enter a parse tree produced by SFMLParser#IntervalSpace.
    def enterIntervalSpace(self, ctx:SFMLParser.IntervalSpaceContext):
        pass

    # Exit a parse tree produced by SFMLParser#IntervalSpace.
    def exitIntervalSpace(self, ctx:SFMLParser.IntervalSpaceContext):
        pass


    # Enter a parse tree produced by SFMLParser#IntervalNoSpace.
    def enterIntervalNoSpace(self, ctx:SFMLParser.IntervalNoSpaceContext):
        pass

    # Exit a parse tree produced by SFMLParser#IntervalNoSpace.
    def exitIntervalNoSpace(self, ctx:SFMLParser.IntervalNoSpaceContext):
        pass


    # Enter a parse tree produced by SFMLParser#block.
    def enterBlock(self, ctx:SFMLParser.BlockContext):
        pass

    # Exit a parse tree produced by SFMLParser#block.
    def exitBlock(self, ctx:SFMLParser.BlockContext):
        pass


    # Enter a parse tree produced by SFMLParser#statement.
    def enterStatement(self, ctx:SFMLParser.StatementContext):
        pass

    # Exit a parse tree produced by SFMLParser#statement.
    def exitStatement(self, ctx:SFMLParser.StatementContext):
        pass


    # Enter a parse tree produced by SFMLParser#forgetStatement.
    def enterForgetStatement(self, ctx:SFMLParser.ForgetStatementContext):
        pass

    # Exit a parse tree produced by SFMLParser#forgetStatement.
    def exitForgetStatement(self, ctx:SFMLParser.ForgetStatementContext):
        pass


    # Enter a parse tree produced by SFMLParser#inputStatement.
    def enterInputStatement(self, ctx:SFMLParser.InputStatementContext):
        pass

    # Exit a parse tree produced by SFMLParser#inputStatement.
    def exitInputStatement(self, ctx:SFMLParser.InputStatementContext):
        pass


    # Enter a parse tree produced by SFMLParser#outputStatement.
    def enterOutputStatement(self, ctx:SFMLParser.OutputStatementContext):
        pass

    # Exit a parse tree produced by SFMLParser#outputStatement.
    def exitOutputStatement(self, ctx:SFMLParser.OutputStatementContext):
        pass


    # Enter a parse tree produced by SFMLParser#inputResourceLimits.
    def enterInputResourceLimits(self, ctx:SFMLParser.InputResourceLimitsContext):
        pass

    # Exit a parse tree produced by SFMLParser#inputResourceLimits.
    def exitInputResourceLimits(self, ctx:SFMLParser.InputResourceLimitsContext):
        pass


    # Enter a parse tree produced by SFMLParser#outputResourceLimits.
    def enterOutputResourceLimits(self, ctx:SFMLParser.OutputResourceLimitsContext):
        pass

    # Exit a parse tree produced by SFMLParser#outputResourceLimits.
    def exitOutputResourceLimits(self, ctx:SFMLParser.OutputResourceLimitsContext):
        pass


    # Enter a parse tree produced by SFMLParser#resourceLimitList.
    def enterResourceLimitList(self, ctx:SFMLParser.ResourceLimitListContext):
        pass

    # Exit a parse tree produced by SFMLParser#resourceLimitList.
    def exitResourceLimitList(self, ctx:SFMLParser.ResourceLimitListContext):
        pass


    # Enter a parse tree produced by SFMLParser#resourceLimit.
    def enterResourceLimit(self, ctx:SFMLParser.ResourceLimitContext):
        pass

    # Exit a parse tree produced by SFMLParser#resourceLimit.
    def exitResourceLimit(self, ctx:SFMLParser.ResourceLimitContext):
        pass


    # Enter a parse tree produced by SFMLParser#QuantityRetentionLimit.
    def enterQuantityRetentionLimit(self, ctx:SFMLParser.QuantityRetentionLimitContext):
        pass

    # Exit a parse tree produced by SFMLParser#QuantityRetentionLimit.
    def exitQuantityRetentionLimit(self, ctx:SFMLParser.QuantityRetentionLimitContext):
        pass


    # Enter a parse tree produced by SFMLParser#RetentionLimit.
    def enterRetentionLimit(self, ctx:SFMLParser.RetentionLimitContext):
        pass

    # Exit a parse tree produced by SFMLParser#RetentionLimit.
    def exitRetentionLimit(self, ctx:SFMLParser.RetentionLimitContext):
        pass


    # Enter a parse tree produced by SFMLParser#QuantityLimit.
    def enterQuantityLimit(self, ctx:SFMLParser.QuantityLimitContext):
        pass

    # Exit a parse tree produced by SFMLParser#QuantityLimit.
    def exitQuantityLimit(self, ctx:SFMLParser.QuantityLimitContext):
        pass


    # Enter a parse tree produced by SFMLParser#quantity.
    def enterQuantity(self, ctx:SFMLParser.QuantityContext):
        pass

    # Exit a parse tree produced by SFMLParser#quantity.
    def exitQuantity(self, ctx:SFMLParser.QuantityContext):
        pass


    # Enter a parse tree produced by SFMLParser#retention.
    def enterRetention(self, ctx:SFMLParser.RetentionContext):
        pass

    # Exit a parse tree produced by SFMLParser#retention.
    def exitRetention(self, ctx:SFMLParser.RetentionContext):
        pass


    # Enter a parse tree produced by SFMLParser#resourceExclusion.
    def enterResourceExclusion(self, ctx:SFMLParser.ResourceExclusionContext):
        pass

    # Exit a parse tree produced by SFMLParser#resourceExclusion.
    def exitResourceExclusion(self, ctx:SFMLParser.ResourceExclusionContext):
        pass


    # Enter a parse tree produced by SFMLParser#Resource.
    def enterResource(self, ctx:SFMLParser.ResourceContext):
        pass

    # Exit a parse tree produced by SFMLParser#Resource.
    def exitResource(self, ctx:SFMLParser.ResourceContext):
        pass


    # Enter a parse tree produced by SFMLParser#StringResource.
    def enterStringResource(self, ctx:SFMLParser.StringResourceContext):
        pass

    # Exit a parse tree produced by SFMLParser#StringResource.
    def exitStringResource(self, ctx:SFMLParser.StringResourceContext):
        pass


    # Enter a parse tree produced by SFMLParser#resourceIdList.
    def enterResourceIdList(self, ctx:SFMLParser.ResourceIdListContext):
        pass

    # Exit a parse tree produced by SFMLParser#resourceIdList.
    def exitResourceIdList(self, ctx:SFMLParser.ResourceIdListContext):
        pass


    # Enter a parse tree produced by SFMLParser#resourceIdDisjunction.
    def enterResourceIdDisjunction(self, ctx:SFMLParser.ResourceIdDisjunctionContext):
        pass

    # Exit a parse tree produced by SFMLParser#resourceIdDisjunction.
    def exitResourceIdDisjunction(self, ctx:SFMLParser.ResourceIdDisjunctionContext):
        pass


    # Enter a parse tree produced by SFMLParser#with.
    def enterWith(self, ctx:SFMLParser.WithContext):
        pass

    # Exit a parse tree produced by SFMLParser#with.
    def exitWith(self, ctx:SFMLParser.WithContext):
        pass


    # Enter a parse tree produced by SFMLParser#WithConjunction.
    def enterWithConjunction(self, ctx:SFMLParser.WithConjunctionContext):
        pass

    # Exit a parse tree produced by SFMLParser#WithConjunction.
    def exitWithConjunction(self, ctx:SFMLParser.WithConjunctionContext):
        pass


    # Enter a parse tree produced by SFMLParser#WithParen.
    def enterWithParen(self, ctx:SFMLParser.WithParenContext):
        pass

    # Exit a parse tree produced by SFMLParser#WithParen.
    def exitWithParen(self, ctx:SFMLParser.WithParenContext):
        pass


    # Enter a parse tree produced by SFMLParser#WithNegation.
    def enterWithNegation(self, ctx:SFMLParser.WithNegationContext):
        pass

    # Exit a parse tree produced by SFMLParser#WithNegation.
    def exitWithNegation(self, ctx:SFMLParser.WithNegationContext):
        pass


    # Enter a parse tree produced by SFMLParser#WithTag.
    def enterWithTag(self, ctx:SFMLParser.WithTagContext):
        pass

    # Exit a parse tree produced by SFMLParser#WithTag.
    def exitWithTag(self, ctx:SFMLParser.WithTagContext):
        pass


    # Enter a parse tree produced by SFMLParser#WithDisjunction.
    def enterWithDisjunction(self, ctx:SFMLParser.WithDisjunctionContext):
        pass

    # Exit a parse tree produced by SFMLParser#WithDisjunction.
    def exitWithDisjunction(self, ctx:SFMLParser.WithDisjunctionContext):
        pass


    # Enter a parse tree produced by SFMLParser#tagMatcher.
    def enterTagMatcher(self, ctx:SFMLParser.TagMatcherContext):
        pass

    # Exit a parse tree produced by SFMLParser#tagMatcher.
    def exitTagMatcher(self, ctx:SFMLParser.TagMatcherContext):
        pass


    # Enter a parse tree produced by SFMLParser#EachSide.
    def enterEachSide(self, ctx:SFMLParser.EachSideContext):
        pass

    # Exit a parse tree produced by SFMLParser#EachSide.
    def exitEachSide(self, ctx:SFMLParser.EachSideContext):
        pass


    # Enter a parse tree produced by SFMLParser#ListedSides.
    def enterListedSides(self, ctx:SFMLParser.ListedSidesContext):
        pass

    # Exit a parse tree produced by SFMLParser#ListedSides.
    def exitListedSides(self, ctx:SFMLParser.ListedSidesContext):
        pass


    # Enter a parse tree produced by SFMLParser#side.
    def enterSide(self, ctx:SFMLParser.SideContext):
        pass

    # Exit a parse tree produced by SFMLParser#side.
    def exitSide(self, ctx:SFMLParser.SideContext):
        pass


    # Enter a parse tree produced by SFMLParser#slotqualifier.
    def enterSlotqualifier(self, ctx:SFMLParser.SlotqualifierContext):
        pass

    # Exit a parse tree produced by SFMLParser#slotqualifier.
    def exitSlotqualifier(self, ctx:SFMLParser.SlotqualifierContext):
        pass


    # Enter a parse tree produced by SFMLParser#rangeset.
    def enterRangeset(self, ctx:SFMLParser.RangesetContext):
        pass

    # Exit a parse tree produced by SFMLParser#rangeset.
    def exitRangeset(self, ctx:SFMLParser.RangesetContext):
        pass


    # Enter a parse tree produced by SFMLParser#range.
    def enterRange(self, ctx:SFMLParser.RangeContext):
        pass

    # Exit a parse tree produced by SFMLParser#range.
    def exitRange(self, ctx:SFMLParser.RangeContext):
        pass


    # Enter a parse tree produced by SFMLParser#ifStatement.
    def enterIfStatement(self, ctx:SFMLParser.IfStatementContext):
        pass

    # Exit a parse tree produced by SFMLParser#ifStatement.
    def exitIfStatement(self, ctx:SFMLParser.IfStatementContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanHas.
    def enterBooleanHas(self, ctx:SFMLParser.BooleanHasContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanHas.
    def exitBooleanHas(self, ctx:SFMLParser.BooleanHasContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanConjunction.
    def enterBooleanConjunction(self, ctx:SFMLParser.BooleanConjunctionContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanConjunction.
    def exitBooleanConjunction(self, ctx:SFMLParser.BooleanConjunctionContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanRedstone.
    def enterBooleanRedstone(self, ctx:SFMLParser.BooleanRedstoneContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanRedstone.
    def exitBooleanRedstone(self, ctx:SFMLParser.BooleanRedstoneContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanDisjunction.
    def enterBooleanDisjunction(self, ctx:SFMLParser.BooleanDisjunctionContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanDisjunction.
    def exitBooleanDisjunction(self, ctx:SFMLParser.BooleanDisjunctionContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanFalse.
    def enterBooleanFalse(self, ctx:SFMLParser.BooleanFalseContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanFalse.
    def exitBooleanFalse(self, ctx:SFMLParser.BooleanFalseContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanParen.
    def enterBooleanParen(self, ctx:SFMLParser.BooleanParenContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanParen.
    def exitBooleanParen(self, ctx:SFMLParser.BooleanParenContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanNegation.
    def enterBooleanNegation(self, ctx:SFMLParser.BooleanNegationContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanNegation.
    def exitBooleanNegation(self, ctx:SFMLParser.BooleanNegationContext):
        pass


    # Enter a parse tree produced by SFMLParser#BooleanTrue.
    def enterBooleanTrue(self, ctx:SFMLParser.BooleanTrueContext):
        pass

    # Exit a parse tree produced by SFMLParser#BooleanTrue.
    def exitBooleanTrue(self, ctx:SFMLParser.BooleanTrueContext):
        pass


    # Enter a parse tree produced by SFMLParser#comparisonOp.
    def enterComparisonOp(self, ctx:SFMLParser.ComparisonOpContext):
        pass

    # Exit a parse tree produced by SFMLParser#comparisonOp.
    def exitComparisonOp(self, ctx:SFMLParser.ComparisonOpContext):
        pass


    # Enter a parse tree produced by SFMLParser#setOp.
    def enterSetOp(self, ctx:SFMLParser.SetOpContext):
        pass

    # Exit a parse tree produced by SFMLParser#setOp.
    def exitSetOp(self, ctx:SFMLParser.SetOpContext):
        pass


    # Enter a parse tree produced by SFMLParser#labelAccess.
    def enterLabelAccess(self, ctx:SFMLParser.LabelAccessContext):
        pass

    # Exit a parse tree produced by SFMLParser#labelAccess.
    def exitLabelAccess(self, ctx:SFMLParser.LabelAccessContext):
        pass


    # Enter a parse tree produced by SFMLParser#roundrobin.
    def enterRoundrobin(self, ctx:SFMLParser.RoundrobinContext):
        pass

    # Exit a parse tree produced by SFMLParser#roundrobin.
    def exitRoundrobin(self, ctx:SFMLParser.RoundrobinContext):
        pass


    # Enter a parse tree produced by SFMLParser#RawLabel.
    def enterRawLabel(self, ctx:SFMLParser.RawLabelContext):
        pass

    # Exit a parse tree produced by SFMLParser#RawLabel.
    def exitRawLabel(self, ctx:SFMLParser.RawLabelContext):
        pass


    # Enter a parse tree produced by SFMLParser#StringLabel.
    def enterStringLabel(self, ctx:SFMLParser.StringLabelContext):
        pass

    # Exit a parse tree produced by SFMLParser#StringLabel.
    def exitStringLabel(self, ctx:SFMLParser.StringLabelContext):
        pass


    # Enter a parse tree produced by SFMLParser#emptyslots.
    def enterEmptyslots(self, ctx:SFMLParser.EmptyslotsContext):
        pass

    # Exit a parse tree produced by SFMLParser#emptyslots.
    def exitEmptyslots(self, ctx:SFMLParser.EmptyslotsContext):
        pass


    # Enter a parse tree produced by SFMLParser#identifier.
    def enterIdentifier(self, ctx:SFMLParser.IdentifierContext):
        pass

    # Exit a parse tree produced by SFMLParser#identifier.
    def exitIdentifier(self, ctx:SFMLParser.IdentifierContext):
        pass


    # Enter a parse tree produced by SFMLParser#string.
    def enterString(self, ctx:SFMLParser.StringContext):
        pass

    # Exit a parse tree produced by SFMLParser#string.
    def exitString(self, ctx:SFMLParser.StringContext):
        pass


    # Enter a parse tree produced by SFMLParser#number.
    def enterNumber(self, ctx:SFMLParser.NumberContext):
        pass

    # Exit a parse tree produced by SFMLParser#number.
    def exitNumber(self, ctx:SFMLParser.NumberContext):
        pass



del SFMLParser